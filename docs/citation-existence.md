# The citation existence check

Task M2-06, `utux.verification.existence`, by the rules of ADR-0016 and
section 8 of the specification. Only these deterministic rules decide; no
model takes part.

## The rules

A reference exists when all four hold:

1. **It resolves** by its identifier, through these services in order:

   | Scheme | Services |
   | --- | --- |
   | `doi:` | Crossref, then OpenAlex |
   | `arxiv:` | arXiv, then OpenAlex |
   | `pmid:` | OpenAlex (PubMed comes first once M2-07 adds it) |

   A service that says the work does not exist passes the reference on to
   the next. A reference with no identifier, or one of another scheme, is
   `not_found`.
2. **Its title matches.** Both titles are normalised: Unicode NFKC, case
   folding, punctuation removed, runs of whitespace made one space. One
   minus the Levenshtein distance divided by the length of the longer title
   is at least `TITLE_SIMILARITY`, 0.9.
3. **The first author's family name matches.** Where the service gives a
   separate family name, as Crossref does, the two are compared after
   normalisation. Where it gives only a display name, as OpenAlex and arXiv
   do, the cited family name must appear in it as whole words: "van der
   Berg" matches "Anna van der Berg", and "Berg" does not match "Anna
   Bergman". A display name is never split.
4. **The years differ by at most** `YEAR_TOLERANCE`, one, to allow a
   preprint and its published version.

Each failed rule is a reason, in this order: `not_found`, `title_mismatch`,
`author_mismatch`, `year_mismatch`. A field missing on either side fails its
rule.

## The bibliography and its claims

`check_bibliography` checks every reference and keys:

- **removed:** the references for which a rule failed, with their reasons.
  They leave the bibliography.
- **incomplete:** the references no service could answer, because each was
  unavailable, rate limited or gave an invalid answer, and none said the
  work does not exist. An outage is not evidence that a reference is
  invented, so these are kept.

`claims_to_unverify` gives the claims that cite a removed or incomplete
reference. Their status becomes `unverified` (specification section 8), the
operational state of RFC-002 section 3.

References come in as `Reference` records: key, identifier, title, the first
author's family name and year. Reading them from a BibTeX file belongs to
`utux verify` (M2-16).

## Scoring

`utux.evalkit.metrics.existence_metrics` computes the metrics of RFC-002
section 7 for this component:

- the precision and recall of detecting invalid references;
- the false-alarm rate on real references.

The gold set's citation existence items are real references, and real
references with an altered title, first author or year. They are built with
the perturbations (`docs/eval/gold-v0-strategy.md`, section 6), and the
check is scored on them then.
