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

## OpenAlex and arXiv

Task M2-05. Both use the standard library's HTTP, with `utux.sources.http.HttpClient`:
a user agent that names utux and its version, one request at a time, a
minimum interval between requests, at most three attempts for a `429`, a
`5xx` or a network failure (waiting for `Retry-After` when given, never more
than 60 seconds), and answers of at most 10 MB. Both are keyless by default.

| | `OpenAlexSource` | `ArxivSource` |
| --- | --- | --- |
| Identifiers | `doi:`, `pmid:`, `openalex:` | `arxiv:` |
| Interval between requests | 0.1 s (10 a second, the limit without a key) | 3 s (arXiv's terms of use) |
| Text | the abstract, rebuilt exactly from the inverted index, words joined by single spaces | the abstract (`summary`), runs of whitespace made one space |
| `source_version` | `index_abstract` | `preprint` |
| `extraction_method` | `openalex_inverted_index` | `arxiv_api_atom` |
| Licence | the open-access location's licence, if given | not given by the API |
| Contact email | never sent: OpenAlex's current documentation does not say it helps | never sent |
| Key | none by default; with `OPENALEX_API_KEY` set, sent only as `Authorization: Bearer`, and requests may go 30 a second | none |

**Authors.** Both services give each author as one name. The last word is
taken as the family name and the rest as the given name, a rule that is
wrong for some names, such as "van der Berg"; ADR-0016 compares the first
author's family name.

**An OpenAlex abstract** is rebuilt from its inverted index, which maps each
word to its positions; the positions must cover 0 to n - 1 exactly once each,
or the answer is invalid.

**An arXiv feed** that holds a document type or an entity declaration is
refused before it is parsed, so no entity is ever expanded.

Under `local_only`, a search on either is refused; fetch and resolve stay
allowed ([The data policy](data-policy.md)).

The live smoke tests reach both services and are run by the maintainer only:

```bash
uv run pytest -m live tests/integration/test_literature_live.py
```
