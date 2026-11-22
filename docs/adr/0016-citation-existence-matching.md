# ADR-0016: When a cited reference counts as existing

- Status: Accepted
- Date: 2026-11-22

## Context

The first verification check is citation existence: each reference is
resolved by DOI, arXiv id or PMID against Crossref, OpenAlex, arXiv or
PubMed, and "title, authors and year must match". An unresolved reference is
removed from the bibliography and its claims are marked `unverified`
(`docs/spec.md`, section 8). The gold set has a citation-existence component
of real references, invented references and real references with an altered
title, authors or year, scored by the precision and recall of detecting
invalid references and the false-alarm rate on real ones (RFC-002, sections
3 and 7).

Real references differ from the record of the resolver in ways that do not
make them invalid: punctuation, letter case, Unicode forms of the same
characters, a subtitle, an abbreviated or reordered author list, and the
year of a preprint against the year of the published version. An exact
match would remove real references; a loose match would accept altered ones.

## Decision

A reference counts as existing when all of these hold:

1. **It resolves** by its identifier: a DOI through Crossref, an arXiv id
   through arXiv, a PMID through PubMed (M2-07), with OpenAlex as the
   fallback (`docs/plan/M2.md`, M2-06).
2. **Its title matches.** Both titles are normalised: Unicode NFKC, case
   folding, punctuation removed, runs of whitespace made one space. Their
   similarity, one minus the Levenshtein distance divided by the length of
   the longer title, is at least 0.9.
3. **The first author's family name matches**, after the same normalisation.
4. **The year differs by at most one**, to allow a preprint and its
   published version.

Each failed rule is a reason code: `not_found`, `title_mismatch`,
`author_mismatch`, `year_mismatch`. The threshold 0.9 and the year tolerance
are constants, documented, and scored on the citation-existence component of
the gold set, as RFC-002 requires of every threshold.

**This departed from the specification**, which said that title, authors and
year must match: rules 3 and 4 match the first author only, and allow a year
one apart. With this ADR's acceptance, section 8 of the specification states
these rules.

## Alternatives rejected

- **Exact matches of title, every author and the year**, as the
  specification states it literally. Many real references would fail on
  punctuation, a subtitle, a shortened author list or a preprint year, so
  the false-alarm rate on real references would be high.
- **A similarity measure from a library**, or `difflib`'s ratio. The
  Levenshtein ratio is symmetric, has a plain definition that can be worked
  out by hand in tests, and needs no dependency; `difflib`'s ratio is not
  symmetric in general, and by default treats frequent items of sequences of
  200 or more as junk.
- **Matching every author.** Author lists differ in length and order between
  records, so a rule over every author would fail real references; a later
  version matches more authors only if the gold scores show the need.
- **A model judging whether two records are the same work.** Deterministic
  rules decide a reference's existence, as they decide a claim's status
  (ADR-0006).

## Consequences

- Each rule is a pure function of two records, tested on synthetic cases
  worked out by hand, including the edges: a similarity of exactly 0.9, and
  years two apart.
- A reference that fails is reported with its reason, removed from the
  bibliography, and its claims become `unverified` (`docs/spec.md`,
  section 8).
- A real reference whose record lacks a title, an author or a year cannot
  pass the rule that needs it; it is reported with that reason, not passed.
- An altered reference that keeps the title, the first author and a year one
  apart passes. The gold set's altered references measure how often this
  happens.
- Section 8 of the specification states these rules.

## Acceptance

Accepted by the maintainer on 2026-11-22, with the edit-distance similarity
of rule 2. Section 8 of the specification is changed to match.

## Sources

- `docs/spec.md`, section 8 ("Verification checks", citation existence).
- `docs/rfc/RFC-002.md`, section 3 (the citation-existence component) and
  section 7 (its metrics).
- `docs/adr/0006-deterministic-verdict-rules.md`: rules, not models, decide.
- `docs/plan/M2.md`, M2-01 (the recommendation) and M2-06.
