# ADR-0017: LiteratureSource contract

- Status: Accepted
- Date: 2026-11-22

## Context

`LiteratureSource` is one of the three public interfaces (ADR-0004), so its
contract must be kept once it exists. The specification gives it three
operations, `search()`, `fetch()` and `resolve(identifier)`, for OpenAlex,
arXiv, Semantic Scholar and PubMed through BioMCP, several active at once
(`docs/spec.md`, section 5). Citation existence resolves references by
identifier and compares title, first author and year (ADR-0016). Citation
support checks claims against stored text, which is an abstract from a
literature API or structured full text (ADR-0014). Every action is logged
(`docs/spec.md`, section 7, "Event log"), and API responses are cached
across projects (`docs/spec.md`, section 9; task M2-03).

M2-04 asks for the contract with typed results and typed errors, a scripted
source, a conformance suite, and a `literature_call` event for every call
(`docs/plan/M2.md`).

## Decision

1. **Three blocking, thread-safe methods**, as `ModelProvider` has one
   (ADR-0007):
   - `search(query, limit) -> tuple[WorkMetadata, ...]`: at most `limit`
     works, best first. A blank query, or a limit outside 1 to 100, raises
     `ValueError` before any call.
   - `fetch(identifier) -> FetchedSource`: the work's metadata and, where
     the source gives it, its text.
   - `resolve(identifier) -> WorkMetadata`: the work's bibliographic
     metadata.
2. **Identifiers carry their scheme**, such as `doi:10.0000/example`,
   `arxiv:2101.00001` or `pmid:00000000`.
3. **Typed results.** `WorkMetadata` holds the identifier, title, authors
   (family and given name), year, venue and URL; what the source does not
   give is null or empty, never guessed. `FetchedSource` holds the metadata,
   the text, which text it is (`abstract` or `full_text`), the source
   version, the licence the source states, and the extraction method. The
   text, its kind and its extraction method are given together or not at
   all.
4. **Typed errors**, all `LiteratureSourceError`:
   `LiteratureUnavailableError` (the source could not be reached, or its
   server failed; retryable), `LiteratureRateLimitError` (retryable later),
   `LiteratureNotFoundError` (no such work), and
   `LiteratureInvalidResponseError` (the answer is not a valid result).
5. **Name and locality.** A source has two read-only attributes, `name` and
   `is_external`. `is_external` is set per instance, true unless the source
   can show that a query stays on the machine, as for `ModelProvider`.
6. **Logging and caching are the core's.** A source knows nothing of
   projects, events or the cache. The core wraps it in a logged caller that
   writes one `literature_call` event per call and keeps results in the
   machine-wide cache. The event names the source, the operation, the
   identifier or, for a search, only the hash of the query, the status with
   its reason (`literature_unavailable`, `rate_limited`, `not_found`,
   `invalid_response`), the duration, and whether the cache answered. A
   failure is never cached.

## Alternatives rejected

- **One method with an operation argument.** Rejected: the three operations
  take and return different things, and typed methods let the conformance
  suite check each.
- **An asynchronous interface.** Rejected for the reasons of ADR-0007:
  blocking calls are simpler to implement, test and call, and callers that
  need parallel calls use threads.
- **Each source logging and caching itself.** Rejected: every source would
  repeat it, and a source could leave a call unlogged. The core does it once.
- **The query text in the event.** Rejected: a query can carry the words of
  an unpublished manuscript. Only its hash is logged, as model calls log
  hashes of what they send.
- **Raising on a missing title, author or year.** Rejected: many real
  records lack one. The field is null, and ADR-0016 fails the reference with
  a reason where it needs that field.

## Consequences

- The conformance suite (`tests/conformance/literature_source_suite.py`)
  checks points 1 to 5, including the limits of a search, not-found,
  each typed error and concurrent calls; every implementation must pass it.
- The scripted source answers from a catalog, for the tests of everything
  that calls a source.
- The `literature_call` event and its rules are part of the event log, and
  `utux validate` checks them with every event.
- Whether queries to an external source are allowed under the data policy
  `local_only` is decided with the first real source (M2-05), using
  `is_external`, as for model providers.
- The contract cell of `LiteratureSource` in the specification, section 5,
  is updated to the typed form, in its own commit.

### Acceptance, 2026-11-22

Accepted by the maintainer on 2026-11-22 as written. Under `local_only`, a
search on an external source is refused before any request, since a query
can carry project text; fetch and resolve by identifier stay allowed
(M2-05).

### Author names, 2026-11-22

Amended at the maintainer's decision in M2-06. Point 3 gave each author a
family and a given name. An author now has `family` and `given`, as Crossref
gives them, or a `display_name`, the whole name as OpenAlex and arXiv give
it, or both; at least one of `family` and `display_name`. A display name is
never split into parts: the first-author rule of ADR-0016 compares the cited
family name with `family` where it is given, and otherwise looks for it as
whole words in `display_name` (`docs/plan/M2.md`, M2-06). The source record
keeps `schema_version` 1, as no release has written source records.

## Sources

- `docs/spec.md`, section 5 ("Six pluggable interfaces", row
  `LiteratureSource`), section 7 ("Event log") and section 9 (the cache).
- `docs/adr/0004-three-public-three-internal-interfaces.md`, and
  `docs/adr/0007-model-provider-contract.md` as the model for this contract.
- `docs/adr/0014-source-text-in-m2.md` and
  `docs/adr/0016-citation-existence-matching.md`.
- `docs/plan/M2.md`, M2-04.
