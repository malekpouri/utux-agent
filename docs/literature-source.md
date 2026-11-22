# The `LiteratureSource` interface

`utux.interfaces.literature_source` (task M2-04, ADR-0017) is the public
interface to a database of scientific works: OpenAlex, arXiv, PubMed and
others. A source does three things, each a blocking call that is safe from
several threads at once:

| Method | Gives | Fails with |
| --- | --- | --- |
| `search(query, limit)` | at most `limit` works (`WorkMetadata`), best first | `ValueError` for a blank query or a limit outside 1 to 100, before any call |
| `fetch(identifier)` | the work and, where the source gives it, its text (`FetchedSource`) | `LiteratureNotFoundError` |
| `resolve(identifier)` | the work's bibliographic metadata (`WorkMetadata`) | `LiteratureNotFoundError` |

Any method can also raise `LiteratureUnavailableError` (retryable),
`LiteratureRateLimitError` (retryable later) and
`LiteratureInvalidResponseError`. A source has a read-only `name` and
`is_external`.

**Identifiers carry their scheme**: `doi:…`, `arxiv:…`, `pmid:…`.

**`WorkMetadata`** holds `identifier`, `title`, `authors` (each a `family`
and a `given` name), `year`, `venue` and `url`. What the source does not
give is null, or empty for the authors; it is never guessed.

**`FetchedSource`** holds `metadata`, `text`, `checked_text` (`abstract` or
`full_text`), `source_version`, `licence` and `extraction_method`. The text,
its kind and its extraction method are given together or not at all.

## Writing a source

An implementation must pass the conformance suite: subclass
`LiteratureSourceConformance` from `tests/conformance/literature_source_suite.py`
and give a source whose catalog holds the suite's known work and a source
that fails in each way. `utux.sources.scripted.ScriptedLiteratureSource`
answers from a catalog and is the source of the tests.

## Logged and cached calls

The core never calls a source directly. `utux.sources.calls.LoggedLiteratureSource`
wraps it:

- every call writes one `literature_call` event ([The event log](event-log.md));
- a search is logged by the hash of its query, never by its text, since a
  query can carry the words of an unpublished manuscript;
- results are kept in the machine-wide cache ([Stored sources and the
  cache](sources.md)), so the same call from any project is answered without
  the network, and the event says so (`cache_hit`). A failure is never kept.

| Failure | `status_reason` |
| --- | --- |
| `LiteratureUnavailableError` | `literature_unavailable` |
| `LiteratureRateLimitError` | `rate_limited` |
| `LiteratureNotFoundError` | `not_found` |
| `LiteratureInvalidResponseError` | `invalid_response` |
